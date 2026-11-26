/*----------------------------------------------------------------------------------------------------------
 * Copyright (c) 1999-2023 by Nuvoton Technology Israel
 * All rights reserved.
 *----------------------------------------------------------------------------------------------------------
 * File Contents:
 *			Validation's 'C' Coding Standards demonstration
 * Project: All
 *----------------------------------------------------------------------------------------------------------*/

/*----------------------------------------------------------------------------------------------------------*/ 
/* Coding Standards general notes:																			*/
/*	- Make sure the editor you are using, is configured to 4 spaces per Tab.								*/
/*	  Otherwise, this code will not be properly viewed.														*/
/*	- In ec_accurev_git, use LogError, LogWarning, LogMessage, or related logging APIs for diagnostics.		*/
/*	  Do not use std::fprintf or write diagnostics directly to stdout or stderr.								*/
/*----------------------------------------------------------------------------------------------------------*/

#include <stdio.h>							// Standard "C" libraries should be placed first
#include <stdlib.h>
#include <Test_If.h>						// Other libraries before local files
#include <TEB2_If.h>
#include "Common.h"							// Common project headers should be placed before other headers
#include "main.h"							// Local headers at the end. If there are several files, keep the same order in all CPP files.

// Definitions are always named in capital letters.
#define	CS_TIMEOUT							35					// Used for test delays demonstration below.

// Typedefs are always in capital letters. The enum typedef's name is used as a prefix for all its elements (prefix isn't added for structs)
typedef enum CS_LIST
{
	CS_LIST_GLOBAL_VAR	= 1,
	CS_LIST_LOCAL_VAR	= 3,
	CS_LIST_FUNC_NAME	= 5,
	CS_LIST_SPACE		= 7,
	CS_LIST_EQUATION	= 11,
	CS_LIST_LINE_LEN	= 13,
	CS_LIST_UNUSED_CODE	= 17
} CS_LIST;

// In most cases, there is need to set the enum elements with specific values. The value of the first element is zero if not specified.
typedef enum CS_FREQ
{
	CS_FREQ_GLOBAL_VAR,
	CS_FREQ_LOCAL_VAR,
	CS_FREQ_NUM								// CS_FREQ_NUM is used as a definition of how many elements are within the enum, instead of defining it elsewhere
} CS_FREQ;

// Typically, exit codes are being managed as part of a Test Template.
// If a template isn't being used, an enum similar to this one should be used when invoking exit() or return from main().
typedef enum EXITCODE
{
	EXITCODE_OK,
	EXITCODE_FILE_NOT_FOUND,
	EXITCODE_TEST_FAILED,
	EXITCODE_BAD_PARAM
} EXITCODE;

bool	StartRunning = true;				// Global variables starts with a capital letter. Don't use 'BOOL', use 'bool' instead.
											// It could be beneficial to add a prefix as well. e.g., "CS_StartRunning".
bool	LogIsEnabled = true;

// Prototypes (typically part of a Header file)
DWORD	CS_ReadNumberOfStandards			(void);				// Functions of a specific module, should start with a prefix. 'CS' stands for "Coding Standards"
bool	CS_Demonstration					(void);				// Align the function's name and parameters of all functions at the same indentation.
void	CS_Exceptions						(void);				// Standard 'C' requires adding "void". There are some compilers that may print a warning if 'void' is absent

// For important and complex functions, please add a function header with a description (see 'CS_Demonstration' function)
DWORD CS_ReadNumberOfStandards()			// After prefix with '_', each word in name starts with a capital letter
{											// Always place the '{' character at a separate line
	DWORD	dataRead;						// Use meaningful variable's name; A local variable always starts with a lowercase letter.

	dataRead = READ_REG(STD_NUM);			// Use spaces around '=' character, i.e., " = "
	return(dataRead & 0x7FFFFFFF);			// Use spaces around '&', '|', '&&' and '||' characters. Do *not* do the following: a=b|c&d;
											// Always use capital letters for hexadecimal numbers, e.g., "0xEC" instead of "0xec".
}

/*----------------------------------------------------------------------------------------------------------*/
/* Function:	CS_Demonstration																			*/
/*																											*/
/* Parameters:  None																						*/
/*																											*/
/* Returns:     'true' - Demonstration passed; 'false' - Demonstration failed;								*/
/*																											*/
/* Description:																								*/
/*		Demonstrate various Coding Standards directives.													*/
/*																											*/
/*		It's possible to use a longer name for this function like "CS_DemonstrateStandards",				*/
/*		though, "Standards" word is already part of "CS" prefix.											*/
/*		Every test and every important function must have this header.										*/
/*----------------------------------------------------------------------------------------------------------*/
bool CS_Demonstration()
{
	DWORD	standardNum;					// Align all variables to the same indentation. Use a meaningful name and *not* 'i', 'j' or 'k' for counters.
	DWORD	numOfStandards;					// Use a meaningful name. It is also possible to use a shorter form, e.g. "numOfStds", though try to avoid it.
	WORD	value;							// Used for demonstrating equations below
	bool	testPassed = true;				// Indicates whether the test has passed

	// Always print an header at a beginning of a test
	LogHeader("Coding Standards Demonstration");

	if (StartRunning)											// When a meaningful name is being used, it possible to eliminate the "== true"
	{
		/*----------------------------*/						// Try to add some separations before a large block of code to ease the orientation (typically larger than below) 
		/* Standards check is enabled */
		/*----------------------------*/

		numOfStandards = CS_ReadNumberOfStandards();

		// Use spaces before and after '=', '<', '>' and '==' characters
		for (standardNum = 0; standardNum < numOfStandards; standardNum++)
		{
			if (LogIsEnabled)
				LogTitle("Demonstrating standard %d out of %d standards\n", standardNum, numOfStandards);

			/*-------------------------*/
			/* Mathematical operations */
			/*-------------------------*/
			if (standardNum == CS_LIST_EQUATION)
			{
				// Add many spaces and parenthesis to ease reading and reduce the chances for bugs
				value = (((numOfStandards & 0xFF) * 3) + 5) | 0x8000;
			}
			/*------------*/
			/* Long lines */
			/*------------*/
			else if (standardNum == CS_LIST_LINE_LEN)
			{
#ifdef DO_NOT_DO
				// The "if" line is too long the whole code doesn't fit in the window
				if ((variableA && VariableB) || (variableA && VariableB) || (variableA && VariableB) || (variableA && VariableB) || (variableA && VariableB) || (variableA && VariableB) || (variableA && VariableB))
				{
					LogMessage("This an example to a code line which is too long. Need to split the line.\n");
					testPassed = false;
				}
#else
				// The same "if" splited to two lines
				if ((variableA && VariableB) || (variableA && VariableB) || (variableA && VariableB) || (variableA && VariableB) || 
					(variableA && VariableB) || (variableA && VariableB) || (variableA && VariableB) )
				{
					LogMessage("This is an example to a long line which has been splitted into two lines.\n");
				}
#endif
			}
			/*-----------------------------------*/
			/* Local variables naming convention */
			/*-----------------------------------*/
			else if (standardNum == CS_LIST_LOCAL_VAR)
			{
				// Local veriables always starts with a lower-case letter. Next word in the variable's name will be uppercase letter.
				BYTE	smbNum;							// SMBus is used as lower-case although SMB is typically used. This is done to preserve the variable's name coding standard.
				BYTE	tebSmbNum;						// Again, same approach, though 'tebSMBNum' could also be used. Underscores are never being used.
				WORD	numOfADCs;						// Since ADCs is the last word, it is more elegant to use it this way instead of 'numOfAdcs'.
				char*	pCurrent;						// Always put the asterisk after the type without spaces. This is true for functions as well.
#ifdef DO_NOT_DO										// Avoid declaring two variables at the same line.
				char*	pBegin, pEnd;					// In addition, in this case 'pBegin' is a pointer while 'pEnd' is a 'char'.
#else
				char*	pBegin;							// Declare each variable with its own line.
				char*	pEnd;
#endif
			}
			/*-------------*/
			/* Unused code */
			/*-------------*/
			else if (standardNum == CS_LIST_UNUSED_CODE)
			{
				// Use #ifdef with a meaningful name related to the disabled code
#ifdef CHIP_REV_A1
				// This code is used for chip rev A1 only and should be deleted in the future
				LogMessage("This is rev A1 only code\n");
#endif
#ifdef ISSUE123_DEBUG
				LogMessage("This code is for debugging Issue #123 and should be removed in the future\n");
#endif
#ifdef DO_NOT_DO
/*
				LogMessage("This is a code for debug and I haven't bothered to delete it, though probably no one will ever use it!\n");
*/
#endif
			}

			// Always describe the reason for a delay. Use the minimal delay required and not just 100ms or 1000ms.
			// If you are uncertain why a delay is required, you should add a comment which describes why a delay has been added.
			// Adding delays when no explanation exists, may cover for a chip issue, or a system issue.
			Delay(CS_TIMEOUT);
		} // standardNum loop
		
		// Always add "PASS!" and "FAIL!" when using LogPass() and LogError() functions
		if (testPassed)
			LogPass("PASS! Coding Standards demonstration (%d standards) completed successfully\n", numOfStandards);
		else
			LogError("FAIL! Coding Standards demonstration has failed!\n");
	} // StartRunning == true
	else
	{
		/*-----------------------------*/
		/* Standards check is disabled */
		/*-----------------------------*/

		if (LogIsEnabled)
			LogMessage("Demonstration is disabled\n");
	}
}

/*----------------------------------------------------------------------------------------------------------*/
/* Function:	CS_Exceptions																				*/
/*																											*/
/* Parameters:  standardNum		- Coding standard code value												*/
/*																											*/
/* Returns:     None																						*/
/*																											*/
/* Description:																								*/
/*		Demonstrates exceptions or special cases in Coding Standards code style.							*/
/*----------------------------------------------------------------------------------------------------------*/
void CS_Exceptions(DWORD standardNum)
{
	/*-------------------------------------------*/
	/* The following code is long and cumbersome */
	/*-------------------------------------------*/

	// Please note that this is only an example and it also applies when more complex than just this list of LogMessage() commands.
	if (standardNum == CS_LIST_GLOBAL_VAR)
	{
		LogMessage("This is the global variable standard\n");
	}
	else if (standardNum == CS_LIST_LOCAL_VAR)
	{
		LogMessage("This is the local variable standard\n");
	}
	else if (standardNum == CS_LIST_FUNC_NAME)
	{
		LogMessage("This is the function's name standard\n");
	}
	else if (standardNum == CS_LIST_SPACE)
	{
		LogMessage("This is the space rules standard\n");
	}
	else if (standardNum == CS_LIST_EQUATION)
	{
		LogMessage("This is the equation rules standard\n");
	}
	else
	{
		LogError("FAIL! Unsupported standard code = %d enetered\n", standardNum);
	}

	/*---------------------------------------------------------*/
	/* The following code is short, elegant and easier to read */
	/*---------------------------------------------------------*/

	// Note that for longer list, an array of strings can be used, though it could be complex.
	// Also, this method is for very basic operations. Do not use it for more complex code.
	if 		(standardNum == CS_LIST_GLOBAL_VAR)	LogMessage("This is the global variable standard\n");
	else if (standardNum == CS_LIST_LOCAL_VAR)	LogMessage("This is the local variable standard\n");
	else if (standardNum == CS_LIST_FUNC_NAME)	LogMessage("This is the function's name standard\n");
	else if (standardNum == CS_LIST_SPACE)		LogMessage("This is the space rules standard\n");
	else if (standardNum == CS_LIST_EQUATION)	LogMessage("This is the equation rules standard\n")
	else
		LogError("FAIL! Unsupported standard code = %d enetered\n", standardNum);
}